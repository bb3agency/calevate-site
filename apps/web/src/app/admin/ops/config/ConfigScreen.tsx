"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { identityAnswerPending, useAdminAccess, useAdminMe } from "@/app/admin/access";
import { KeyManagementPanel, SecretsPanel } from "@/app/admin/ops/SecretsPanel";
import { WithheldPanel } from "@/app/admin/withheld";
import { InfoTip } from "@/components/console/infoTip";
import { SettingsLayout, useActiveSection } from "@/components/console/settingsLayout";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useOpsConfig, type ConfigList } from "@/lib/api/opsConfig";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { ConfigSectionBody } from "./ConfigSection";
import { ConfigSearchBar, ConfigSearchResults } from "./ConfigSearch";
import { ConfigStatus, ConfigUnreadable } from "./ConfigStatus";
import { LiveApplyStatus } from "./LiveApplyStatus";
import { configState, type ConfigState } from "./configField";
import { WithheldSettings } from "./configPanels";
import {
  CREDENTIALS_SECTION,
  CONFIG_ROUTE,
  SETTINGS_FALLBACK,
  deepLinkAnchor,
  isFiltering,
  screenSections,
  sectionAnchor,
  servedSections,
  type ConfigFilter,
} from "./configSections";

type Access = ReturnType<typeof useAdminAccess>;

const NO_FILTER: ConfigFilter = { query: "", changedOnly: false };

/**
 * PLATFORM CONFIGURATION — every setting this deployment can change without logging into
 * the server, and the vendor keys it signs in with, one subject per section (D-661).
 *
 * Job: find one setting, see its value and who set it, and change it safely.
 *
 * The sections, their order and which setting sits in which are SERVED with the settings
 * (`GET /v1/ops/config`), so this screen arranges and never guesses. Search and the
 * "differs from default" filter look across every section at once.
 *
 * Each section gates on ITS OWN permission: `platform:config` for the settings and prices,
 * `platform:secrets` for credentials. Nothing is mounted — and so nothing is requested — for
 * a session the server has refused, because on these surfaces the READ carries the write's
 * permission (`admin/withheld.tsx`). The mount also waits for the identity read to have
 * ANSWERED (`identityAnswerPending`), so nothing appears, populates and is then replaced.
 */
export function ConfigScreen() {
  const mayConfigure = useAdminAccess("platform:config", "change platform configuration");
  const maySecrets = useAdminAccess("platform:secrets", "install or rotate credentials");
  const identityLoading = identityAnswerPending(useAdminMe());

  if (identityLoading || mayConfigure.refused) {
    return (
      <ConfigFrame
        state={null}
        identityLoading={identityLoading}
        mayConfigure={mayConfigure}
        maySecrets={maySecrets}
      />
    );
  }
  return <ReadableConfigScreen mayConfigure={mayConfigure} maySecrets={maySecrets} />;
}

/** Mounted only for a session that may read the configuration, so the read fires only then. */
function ReadableConfigScreen({ mayConfigure, maySecrets }: { mayConfigure: Access; maySecrets: Access }) {
  const query = useOpsConfig();
  const state = configState(query);
  return (
    <ConfigFrame
      state={state}
      identityLoading={false}
      mayConfigure={mayConfigure}
      maySecrets={maySecrets}
      problem={query.error ? <ProblemNotice error={query.error} onRetry={() => query.refetch()} /> : null}
    />
  );
}

function ConfigFrame({
  state,
  identityLoading,
  mayConfigure,
  maySecrets,
  problem = null,
}: {
  /** `null` when this session does not read the configuration at all. */
  state: ConfigState | null;
  identityLoading: boolean;
  mayConfigure: Access;
  maySecrets: Access;
  problem?: ReactNode;
}) {
  const [filter, setFilter] = useState<ConfigFilter>(NO_FILTER);
  const config = state?.status === "read" ? state.config : undefined;
  const served = config ? servedSections(config) : undefined;
  const sections = screenSections(served);
  const active = useActiveSection(sections);
  const spec = sections.find((section) => section.id === active);
  const waiting = identityLoading || state?.status === "loading";
  const filtering = config !== undefined && isFiltering(filter);
  const jump = useJumpTo(() => setFilter(NO_FILTER), !waiting);

  /*
   * DECLARED TO THE SCREEN ASSISTANT WITH NO INVENTORY. Which vendor credentials a
   * deployment holds is a targeting oracle (`apps/api/ops/secret_routes.py`), so no key
   * name, count or "none installed" leaves this screen, not even for a `platform:secrets`
   * holder. What it declares is which section is open and whether this operator may see
   * it, because "why can I not see the credentials" is answered by a permission.
   */
  useCopilotSurface({
    route: CONFIG_ROUTE,
    title: "Platform configuration",
    realm: "admin",
    fields: [],
    facts: [
      { key: "identity", label: "Has the permission check answered", value: identityLoading ? "not yet" : "yes" },
      { key: "section", label: "Section open", value: filtering ? "search results" : (spec?.label ?? active) },
      {
        key: "platform_config",
        label: "Sections on platform:config — every section except credentials",
        value: identityLoading ? "unknown" : mayConfigure.refused ? "withheld" : "shown",
      },
      {
        key: "platform_secrets",
        label: "Section on platform:secrets — credentials and key management",
        value: identityLoading ? "unknown" : maySecrets.refused ? "withheld" : "shown",
      },
      {
        key: "no_inventory",
        label: "What this screen tells Pip about stored credentials",
        value: "nothing — not a key name, not a count",
      },
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <div className="space-y-3">
        <p className="flex items-center gap-1 text-body text-ink-muted">
          Each change needs a reason. Stored keys are never shown.
          <InfoTip label="Platform configuration">
            <p>
              These are the settings you can change without logging into the server, and the
              vendor keys the platform signs in with. A change reaches the whole platform within
              a few seconds, live agents included; a setting that needs a restart or another step is the exception, and
              each row says which it is. A stored key can only be replaced, never shown back.
            </p>
          </InfoTip>
        </p>
        {config && <ConfigStatus config={config} />}
        {config && <LiveApplyStatus />}
        {config && <ConfigSearchBar filter={filter} onChange={setFilter} />}
      </div>

      {waiting ? (
        <div>
          <Skeleton rows={4} label="Loading the platform configuration…" />
        </div>
      ) : filtering && config ? (
        <ConfigSearchResults
          config={config}
          filter={filter}
          access={mayConfigure}
          secretsAccess={maySecrets}
          onClear={() => setFilter(NO_FILTER)}
          onJump={jump}
        />
      ) : (
        <SettingsLayout
          label="Configuration sections"
          sections={sections.map(({ id, label }) => ({ id, label }))}
          renderSection={(id) => (
            <SectionContent
              id={id}
              hint={sections.find((section) => section.id === id)?.hint ?? null}
              state={state}
              config={config}
              mayConfigure={mayConfigure}
              maySecrets={maySecrets}
              problem={problem}
            />
          )}
        />
      )}
    </div>
  );
}

function SectionContent({
  id,
  hint,
  state,
  config,
  mayConfigure,
  maySecrets,
  problem,
}: {
  id: string;
  hint: string | null;
  state: ConfigState | null;
  config: ConfigList | undefined;
  mayConfigure: Access;
  maySecrets: Access;
  problem: ReactNode;
}) {
  const lead = hint ? <p className="-mt-2 mb-4 text-body text-ink-muted">{hint}</p> : null;

  if (id === CREDENTIALS_SECTION.id) {
    // THE SHARPEST EDGE IN EITHER CONSOLE: the withheld cards say what each panel is for
    // and nothing whatever about what is installed.
    const why = maySecrets.reason ?? "Your admin account cannot install or rotate credentials.";
    return (
      <div id={sectionAnchor(id)} className="space-y-5">
        {lead}
        {maySecrets.refused ? (
          <>
            <WithheldPanel
              title="Vendor credentials"
              reason={why}
              subject="This panel would list the key names this deployment holds and the last four characters of each."
            />
            <WithheldPanel
              title="Key management"
              reason={why}
              subject="This panel would show which key-encryption key is active and how many stored versions are still wrapped under an older one."
            />
          </>
        ) : (
          <>
            <SecretsPanel access={maySecrets} />
            <KeyManagementPanel access={maySecrets} />
          </>
        )}
      </div>
    );
  }

  const section = config ? servedSections(config).find((served) => served.id === id) : undefined;
  return (
    <div id={sectionAnchor(id)} className="space-y-5">
      {lead}
      {mayConfigure.refused || state === null ? (
        <WithheldSettings reason={mayConfigure.reason} />
      ) : state.status === "forbidden" ? (
        <WithheldPanel
          title="Platform configuration"
          reason={
            state.said ??
            "The API refused this read: your admin account may not see the platform configuration."
          }
          subject="This panel would list every setting this deployment can change without logging into the server, and the value in force for each."
        />
      ) : state.status === "unreadable" ? (
        <>
          {problem}
          <ConfigUnreadable />
        </>
      ) : config && section ? (
        <ConfigSectionBody section={section} config={config} access={mayConfigure} />
      ) : (
        // Unreachable while the menu is built from the same read; said rather than blank.
        <p className="text-body text-ink-muted">
          {SETTINGS_FALLBACK.hint} This section is not in the list the platform served.
        </p>
      )}
    </div>
  );
}

/** How long a search hit stays highlighted after the jump. */
const HIGHLIGHT_MS = 2500;
/** How long the jump waits for its target to render: a panel reads its own data first. */
const FIND_TARGET_MS = 3000;
const HIGHLIGHT = ["ring-2", "ring-brand", "ring-offset-2"];

/**
 * A search result's jump: clear the search, open the section that holds the target, then
 * scroll to it and outline it briefly once it has rendered. The section is a URL param, so
 * Back returns to where the operator was.
 *
 * A deep link from another screen (`configHref`: `?section=…&panel=…`, `&credential=…` or
 * `&setting=…`) lands through the same find, scroll and outline once the screen has read
 * what it shows (`ready`), and once per link, so the outline does not come back on every
 * re-render.
 */
function useJumpTo(clearSearch: () => void, ready: boolean): (section: string, anchor: string) => void {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [target, setTarget] = useState<string | null>(null);
  const deepLink = deepLinkAnchor(params);
  const [landed, setLanded] = useState<string | null>(null);
  const linked = ready && deepLink !== null && deepLink !== landed ? deepLink : null;
  const anchor = target ?? linked;

  useEffect(() => {
    if (anchor === null) return;
    const finish = () => {
      setTarget(null);
      if (linked !== null) setLanded(linked);
    };
    const started = Date.now();
    let frame = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const find = () => {
      const element = document.getElementById(anchor);
      if (element) {
        element.scrollIntoView?.({ block: "start", behavior: reduce ? "auto" : "smooth" });
        element.classList.add(...HIGHLIGHT);
        element.setAttribute("data-search-hit", "true");
        timer = setTimeout(() => {
          element.classList.remove(...HIGHLIGHT);
          element.removeAttribute("data-search-hit");
          finish();
        }, HIGHLIGHT_MS);
        return;
      }
      if (Date.now() - started < FIND_TARGET_MS) frame = requestAnimationFrame(find);
      else finish();
    };
    frame = requestAnimationFrame(find);
    return () => {
      cancelAnimationFrame(frame);
      if (timer) clearTimeout(timer);
    };
  }, [anchor, linked]);

  return (section, jumpTo) => {
    clearSearch();
    const next = new URLSearchParams(params.toString());
    next.set("section", section);
    for (const name of ["panel", "credential", "setting"]) next.delete(name);
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
    setTarget(jumpTo);
  };
}
