"use client";

import { Search, X } from "lucide-react";

import { FIELD, FilterChip, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { ConfigList } from "@/lib/api/opsConfig";

import { SettingsList } from "./ConfigSection";
import { filterAcrossSections, type ConfigFilter } from "./configSections";

type Access = { allowed: boolean; reason: string | null };

/**
 * Find a setting across every section: words typed match its name, key, variable,
 * description, section or value, and "Differs from default" narrows to what somebody
 * changed. While a filter is on, the screen shows the matches instead of one section.
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
      <label className="relative block sm:flex-1">
        <span className="sr-only">Search settings</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
        />
        <input
          type="search"
          value={filter.query}
          onChange={(event) => onChange({ ...filter, query: event.target.value })}
          placeholder="Search settings, e.g. tier, carrier, GST"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          enterKeyHint="search"
          className={`${FIELD} pl-9`}
        />
      </label>
      <FilterChip
        label="Differs from default"
        active={filter.changedOnly}
        onClick={() => onChange({ ...filter, changedOnly: !filter.changedOnly })}
      />
    </div>
  );
}

export function ConfigSearchResults({
  config,
  filter,
  access,
  onClear,
}: {
  config: ConfigList;
  filter: ConfigFilter;
  access: Access;
  onClear: () => void;
}) {
  const groups = filterAcrossSections(config, filter);
  const count = groups.reduce((total, group) => total + group.fields.length, 0);

  return (
    <section aria-labelledby="config-search-heading" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="config-search-heading" className="text-[17px] font-semibold text-ink">
          Matching settings
        </h2>
        <button type="button" onClick={onClear} className={SECONDARY_BUTTON_SM}>
          <X aria-hidden className="h-3.5 w-3.5" />
          Clear search
        </button>
      </div>
      {/* Polite: the count follows typing and must not interrupt it. */}
      <p role="status" className="text-sm text-ink-muted">
        {count === 0
          ? "No setting matches. Panels such as the rate card and model prices are not searched; open their section."
          : `${count === 1 ? "1 setting" : `${count} settings`} in ${groups.length === 1 ? "1 section" : `${groups.length} sections`}.`}
      </p>
      {groups.map(({ section, fields }) => (
        <section key={section.id} aria-labelledby={`config-search-${section.id}`} className="space-y-2">
          <h3 id={`config-search-${section.id}`} className="text-sm font-semibold text-ink">
            {section.label}
          </h3>
          <SettingsList fields={fields} access={access} />
        </section>
      ))}
    </section>
  );
}
