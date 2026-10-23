"use client";

import { ArrowRight, X } from "lucide-react";

import { INR_MODEL_LABELS } from "@/app/admin/ops/ModelPricingPanel";
import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { SearchField } from "@/components/arc/search-field";
import { FilterChip, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { ConfigList } from "@/lib/api/opsConfig";
import { useInrLlmPrices, useModelPrices } from "@/lib/api/opsModelPricing";
import { useSecrets } from "@/lib/api/opsSecrets";
import { lookup } from "@/lib/lookup";

import { SettingsList } from "./ConfigSection";
import {
  filterAcrossSections,
  matchTargets,
  screenSections,
  searchTargets,
  sectionAnchor,
  servedSections,
  suggestedSection,
  type ConfigFilter,
  type SearchTarget,
} from "./configSections";

type Access = { allowed: boolean; reason: string | null };

/**
 * Find anything on the configuration screen: a setting (its name, key, variable,
 * description, section or value), a section, a panel (by its title, what it holds and the
 * names it lists, such as a model id), or a credential by its name. "Edited from default"
 * narrows the settings to what somebody changed. While a filter is on, the screen shows the
 * matches instead of one section, and each match jumps to its place.
 */
export function ConfigSearchBar({
  filter,
  onChange,
}: {
  filter: ConfigFilter;
  onChange: (next: ConfigFilter) => void;
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      {/* Filtered on every keystroke: the index is local, so there is nothing to debounce. */}
      <SearchField
        label="Search settings, panels and credentials"
        hideLabel
        className="sm:flex-1"
        value={filter.query}
        onValueChange={(query) => onChange({ ...filter, query })}
        placeholder="Search settings, e.g. trial, carrier, GST"
        autoCorrect="off"
        autoCapitalize="off"
        slashToFocus
      />
      <FilterChip
        label="Edited from default"
        active={filter.changedOnly}
        onClick={() => onChange({ ...filter, changedOnly: !filter.changedOnly })}
      />
    </div>
  );
}

/**
 * The model ids and names the Model prices panel lists, for the search index, and whether a
 * read behind them failed (then the panel is still found by its title, and the results say
 * the model names were not searched rather than implying there are none).
 */
function useModelNames(): { names: string[]; failed: boolean } {
  const dollars = useModelPrices();
  const rupees = useInrLlmPrices();
  const names: string[] = [];
  if (dollars.data) {
    for (const price of dollars.data.prices) names.push(price.model);
    for (const row of dollars.data.tts_prices) names.push(row.provider, row.tts_model, row.tier_label);
  }
  if (rupees.data) {
    for (const row of rupees.data.prices) {
      names.push(row.model);
      const label = lookup(INR_MODEL_LABELS, row.model);
      if (label) names.push(label);
    }
  }
  return { names: names.filter(Boolean), failed: dollars.isError || rupees.isError };
}

export function ConfigSearchResults({
  config,
  filter,
  access,
  secretsAccess,
  onClear,
  onJump,
}: {
  config: ConfigList;
  filter: ConfigFilter;
  access: Access;
  /** Whether this viewer may read credential names; never their values. */
  secretsAccess: Access;
  onClear: () => void;
  onJump: (section: string, anchor: string) => void;
}) {
  const secrets = useSecrets(secretsAccess.allowed);
  const models = useModelNames();
  // Names only, and only for a viewer who may read them; a failed read searches none and
  // says so below.
  const credentialKeys =
    secretsAccess.allowed && secrets.data ? secrets.data.secrets.map((secret) => secret.key) : null;
  const unsearched = [
    models.failed ? "model names (the model price read failed)" : null,
    secretsAccess.allowed && secrets.isError ? "credential names (the credentials read failed)" : null,
  ].filter((item): item is string => item !== null);
  const groups = filterAcrossSections(config, filter);
  const settings = groups.reduce((total, group) => total + group.fields.length, 0);
  // Panels and credentials have no "edited" state, so "Edited from default" shows settings.
  const targets = filter.changedOnly
    ? []
    : matchTargets(searchTargets(config, credentialKeys, { model_pricing: models.names }), filter.query);
  const labels = new Map(screenSections(servedSections(config)).map((s) => [s.id, s.label]));
  const nothing = settings === 0 && targets.length === 0;
  const suggestion = nothing ? suggestedSection(config, filter.query) : null;

  return (
    <section aria-labelledby="config-search-heading" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="config-search-heading" className="text-heading text-ink">
          Search results
        </h2>
        <button type="button" onClick={onClear} className={SECONDARY_BUTTON_SM}>
          <X aria-hidden className="h-3.5 w-3.5" />
          Clear search
        </button>
      </div>
      {/* Polite: the count follows typing and must not interrupt it. */}
      <p role="status" className="text-body text-ink-muted">
        {nothing
          ? `Nothing on this screen matches${filter.query.trim() ? ` "${filter.query.trim()}"` : ""}.`
          : resultSummary(settings, groups.length, targets.length)}
      </p>
      {unsearched.length > 0 && (
        <p className="text-meta text-ink-muted">Not searched: {unsearched.join("; ")}.</p>
      )}
      {suggestion && (
        <p className="text-body text-ink-muted">
          Try browsing{" "}
          <button
            type="button"
            className="font-medium text-brand underline underline-offset-2"
            onClick={() => onJump(suggestion.id, sectionAnchor(suggestion.id))}
          >
            {suggestion.label}
          </button>
          , or clear the search to see every section.
        </p>
      )}
      {targets.length > 0 && (
        <section aria-labelledby="config-search-places" className="space-y-2">
          <h3 id="config-search-places" className="text-body font-semibold text-ink">
            Sections, panels and credentials
          </h3>
          <ul className="divide-y divide-line border-y border-line">
            {targets.map((target) => (
              <li key={target.anchor}>
                <TargetRow
                  target={target}
                  sectionLabel={labels.get(target.section) ?? target.section}
                  onJump={onJump}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
      {groups.map(({ section, fields }) => (
        <section key={section.id} aria-labelledby={`config-search-${section.id}`} className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id={`config-search-${section.id}`} className="text-body font-semibold text-ink">
              {section.label}
            </h3>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => onJump(section.id, sectionAnchor(section.id))}
            >
              Open section
              <ArrowRight aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
          <SettingsList fields={fields} access={access} />
        </section>
      ))}
    </section>
  );
}

function resultSummary(settings: number, sections: number, places: number): string {
  const parts: string[] = [];
  if (settings > 0) {
    parts.push(
      `${settings === 1 ? "1 setting" : `${settings} settings`} in ${sections === 1 ? "1 section" : `${sections} sections`}`,
    );
  }
  if (places > 0) parts.push(places === 1 ? "1 section, panel or credential" : `${places} sections, panels or credentials`);
  return `${parts.join(" and ")}.`;
}

const KIND_LABEL: Record<SearchTarget["kind"], string> = {
  section: "Section",
  panel: "Panel",
  credential: "Credential",
};

function TargetRow({
  target,
  sectionLabel,
  onJump,
}: {
  target: SearchTarget;
  sectionLabel: string;
  onJump: (section: string, anchor: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onJump(target.section, target.anchor)}
      className="flex w-full items-start justify-between gap-3 py-3 text-left hover:bg-surface-sunken sm:px-2"
    >
      <span className="min-w-0">
        <span className="block text-body text-ink">
          {target.kind === "credential" ? <MonoValue>{target.title}</MonoValue> : target.title}
        </span>
        <span className="mt-0.5 block text-meta text-ink-muted">
          {KIND_LABEL[target.kind]}
          {target.kind !== "section" ? ` in ${sectionLabel}` : ""}. {target.detail}
        </span>
      </span>
      <ArrowRight aria-hidden className="mt-1 h-4 w-4 shrink-0 text-ink-muted" />
    </button>
  );
}
