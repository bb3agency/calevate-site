"use client";

import { Section } from "@/components/console/section";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";

import { SectionEditor, stepProblem } from "@/components/businessProfile/SectionEditor";
import { ConfirmDialog } from "@/components/confirmDialog";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { SegmentedControl, type SegmentedOption } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useAgentLanguageChoices } from "@/lib/api/agentLanguages";
import {
  STEPS_MODE,
  draftFromProfile,
  setupHref,
  stepsFor,
  useBusinessProfile,
  wordingFacts,
  type BusinessProfile,
  type ProfileDraft,
} from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { UnsavedRegistry, type UnsavedRegistryValue } from "@/lib/useUnsavedGuard";

import { SetupChecklist } from "../../SetupChecklist";
import { BusinessCopySection } from "./BusinessCopySection";
import { ProfileSection } from "./ProfileSection";
import { SetupWizard } from "./SetupWizard";

const MODES: SegmentedOption[] = [
  { value: "all", label: "All answers" },
  { value: STEPS_MODE, label: "One at a time" },
];

/**
 * Business profile: the business's facts, which every agent of the account answers with
 * (D-695). Two ways through the same facts, saved by the same call: every topic on one
 * page, or one question at a time (`?mode=steps`, where a new client starts and where the
 * dashboard's next steps resume). One screen rather than two sidebar entries, so a client
 * never wonders which of them holds the answer.
 */
export function BusinessProfileScreen() {
  const { session, href: realmHref } = useClientRealm();
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const router = useRouter();
  const params = useSearchParams();
  const steps = params.get("mode") === STEPS_MODE;
  // Switching mode unmounts the other way's forms and their typing with them, and
  // `beforeunload` never sees an in-app move. The sections report their unsaved edits here
  // (`useUnsavedGuard`), the same registry `SettingsLayout` keeps, and the switch asks first.
  const drafts = useRef(new Set<string>());
  const registry = useMemo<UnsavedRegistryValue>(
    () => ({
      report: (id, dirty) => {
        if (dirty) drafts.current.add(id);
        else drafts.current.delete(id);
      },
    }),
    [],
  );
  const [pending, setPending] = useState<string | null>(null);
  const go = (mode: string) =>
    router.replace(mode === STEPS_MODE ? setupHref(href) : href("/settings/business"), { scroll: false });
  return (
    <div className="space-y-5">
      <SegmentedControl
        label="How to answer"
        options={MODES}
        value={steps ? STEPS_MODE : "all"}
        onValueChange={(mode) => {
          if (mode === (steps ? STEPS_MODE : "all")) return;
          if (drafts.current.size > 0) setPending(mode);
          else go(mode);
        }}
        fill
      />
      <UnsavedRegistry.Provider value={registry}>
        {steps ? <SetupWizard /> : <AllAnswers />}
      </UnsavedRegistry.Provider>
      {pending !== null ? (
        <ConfirmDialog
          title="Leave without saving?"
          confirmLabel="Discard changes"
          pendingLabel="Discarding…"
          cancelLabel="Keep editing"
          pending={false}
          error={null}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const to = pending;
            setPending(null);
            drafts.current.clear();
            go(to);
          }}
        >
          <p>Your changes to the business profile have not been saved.</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

/** Every topic on one page, each saved on its own, so fixing a price never resends the
 *  hours. Readable by everyone on the account; editable by an owner, and by an operator in
 *  a view-as session. */
function AllAnswers() {
  const { session, href: realmHref } = useClientRealm();
  // Paths below are relative to this account: "/verify-business" is /c/<slug>/verify-business.
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const profile = useBusinessProfile(session);
  const write = useWriteAccess(session, "org:manage", "change the business profile");

  useCopilotSurface({
    route: "/c/{slug}/settings/business",
    title: "Business profile",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: profile.data
          ? "the business profile has loaded"
          : profile.error
            ? "the profile failed to load"
            : "still loading",
      },
      ...(profile.data
        ? [
            {
              key: "still_needed",
              label: "What agents still need before they can take calls",
              value: profile.data.blockers.map((b) => b.message).join(" ") || "nothing",
            },
            ...wordingFacts(profile.data.wording),
          ]
        : []),
    ],
    apply: noFill,
  });

  if (profile.isPending) return <Skeleton rows={8} />;
  if (profile.isError)
    return <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />;
  return (
    <>
      <Profile profile={profile.data} href={href} canWrite={write.allowed} reason={write.reason} />
      <div className="mt-5 max-w-3xl">
        <BusinessCopySection session={session} canWrite={write.allowed} />
      </div>
    </>
  );
}

function Profile({
  profile,
  href,
  canWrite,
  reason,
}: {
  profile: BusinessProfile;
  href: (path: string) => string;
  canWrite: boolean;
  reason: string | null;
}) {
  // Seeded once; each section saves its own topic, and this draft keeps whatever is
  // being typed in the other sections.
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFromProfile(profile));
  const saved = draftFromProfile(profile);
  const languages = useAgentLanguageChoices(useClientRealm().session);

  return (
    <div className="max-w-3xl space-y-5">
      {reason && <RestrictionNote reason={reason} />}
      <SetupChecklist />

      <Section title="Your business">
        <SettingRows>
          <SettingRow
            label="Business name"
            value={<span className="break-words">{profile.business_name}</span>}
          />
          <SettingRow
            label="Legal name"
            hint="From your verification."
            value={
              profile.legal_name ? (
                <span className="break-words">{profile.legal_name}</span>
              ) : (
                <Link
                  href={href("/verify-business")}
                  className="font-medium text-brand-strong hover:underline touch:inline-flex touch:min-h-11 touch:items-center"
                >
                  Verify your business
                </Link>
              )
            }
          />
        </SettingRows>
      </Section>

      {stepsFor(profile.wording).map((step) => (
        <ProfileSection
          key={step.id}
          step={step}
          draft={draft}
          saved={saved}
          canWrite={canWrite}
          onDraft={setDraft}
          problem={stepProblem(draft, step.id)}
          render={(errorAt) => (
            <SectionEditor
              step={step.id}
              draft={draft}
              onChange={setDraft}
              disabled={!canWrite}
              errorAt={errorAt}
              wording={profile.wording}
              languages={languages}
            />
          )}
        />
      ))}
    </div>
  );
}
