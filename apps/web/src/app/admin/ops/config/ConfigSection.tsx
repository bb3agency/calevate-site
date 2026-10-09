"use client";

import { Disclosure } from "@/components/ui";
import { SettingRows } from "@/components/console/settingRow";
import type { ConfigField, ConfigList, ConfigSection } from "@/lib/api/opsConfig";

import { ConfigRow } from "./ConfigRow";
import { displayValue } from "./configControl";
import { ConfigPanel } from "./configPanels";
import { fieldsIn, groupFields, type FieldGroup } from "./configSections";

type Access = { allowed: boolean; reason: string | null };

/**
 * One served section: the panels the server placed before its settings, the settings in
 * their subsections, then the panels after.
 *
 * Settings the current engine does not read are set apart in a closed disclosure whose
 * closed state says how many there are and which engine is in force (UX-DOCTRINE §3: the
 * fact stays readable, the click buys the controls). They stay editable — an operator
 * preparing an engine switch sets them before the switch.
 */
export function ConfigSectionBody({
  section,
  config,
  access,
}: {
  section: ConfigSection;
  config: ConfigList;
  access: Access;
}) {
  const fields = fieldsIn(section, config);
  const { groups, unused } = groupFields(section, fields);
  const engine = config.fields.find((field) => field.key === "engine");

  return (
    <>
      {section.panels_before.map((id) => (
        <ConfigPanel key={id} id={id} access={access} config={config} />
      ))}
      {groups.map((group) => (
        <SettingsGroup key={group.id} group={group} access={access} />
      ))}
      {unused.length > 0 && (
        <Disclosure
          title="Not used by the current engine"
          headingLevel={3}
          subtitle={
            <>
              {unused.length === 1 ? "1 setting" : `${unused.length} settings`} only another
              engine reads. The engine in force is {engine ? displayValue(engine, engine.value) : "unknown"}.
            </>
          }
        >
          <SettingsList fields={unused} access={access} label="Settings not used by the current engine" />
        </Disclosure>
      )}
      {fields.length === 0 && section.panels_before.length + section.panels_after.length === 0 && (
        // A statement from a read that ARRIVED.
        <p className="rounded-card border border-line px-4 py-6 text-center text-sm text-ink-muted">
          This deployment has no settings in this section.
        </p>
      )}
      {section.panels_after.map((id) => (
        <ConfigPanel key={id} id={id} access={access} config={config} />
      ))}
    </>
  );
}

function SettingsGroup({ group, access }: { group: FieldGroup; access: Access }) {
  const headingId = `config-group-${group.id}`;
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <h3 id={headingId} className="text-sm font-semibold text-ink">
        {group.label}
      </h3>
      <SettingsList fields={group.fields} access={access} />
    </section>
  );
}

/** Rows of settings inside one bordered list. */
export function SettingsList({
  fields,
  access,
  label,
}: {
  fields: readonly ConfigField[];
  access: Access;
  label?: string;
}) {
  return (
    <div
      role={label ? "group" : undefined}
      aria-label={label}
      className="rounded-card border border-line bg-surface px-4 sm:px-5"
    >
      <SettingRows>
        {fields.map((field) => (
          <ConfigRow key={field.key} field={field} access={access} />
        ))}
      </SettingRows>
    </div>
  );
}
