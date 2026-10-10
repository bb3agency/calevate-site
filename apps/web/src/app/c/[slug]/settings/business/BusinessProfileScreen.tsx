"use client";

import { Section } from "@/components/console/section";

import Link from "next/link";
import { useState } from "react";

import { ProfileBlockers } from "@/components/businessProfile/ProfileBlockers";
import { SectionEditor, stepProblem } from "@/components/businessProfile/SectionEditor";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  STEPS,
  draftFromProfile,
  useBusinessProfile,
  type BusinessProfile,
  type ProfileDraft,
} from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { SetupChecklist } from "../../SetupChecklist";
import { ProfileSection } from "./ProfileSection";

/**
 * Business profile: the business's facts, which every agent of the account answers with
 * (D-695). Primary job: change a fact and have every agent say it, with no publishing.
 *
 * One section per topic, each saved on its own, so fixing a price never resends the hours.
 * Readable by everyone on the account; editable by an owner, and by an operator in a
 * view-as session.
 */
export function BusinessProfileScreen() {
  const { session, href: realmHref } = useClientRealm();
  // Paths below are relative to this account: "/setup" is /c/<slug>/setup.
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
          ]
        : []),
    ],
    apply: noFill,
  });

  if (profile.isPending) return <Skeleton rows={8} />;
  if (profile.isError)
    return <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />;
  return (
    <Profile profile={profile.data} href={href} canWrite={write.allowed} reason={write.reason} />
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

  return (
    <div className="max-w-3xl space-y-5">
      {reason && <RestrictionNote reason={reason} />}
      <ProfileBlockers blockers={profile.blockers} href={href} />
      <SetupChecklist placement="settings" />

      <Section title="Your business">
        <SettingRows>
          <SettingRow
            label="Business name"
            value={<span className="break-words">{profile.business_name}</span>}
          />
          <SettingRow
            label="Legal name"
            hint="From your business verification, and changed there."
            value={
              profile.legal_name ? (
                <span className="break-words">{profile.legal_name}</span>
              ) : (
                <Link
                  href={href("/verify-business")}
                  className="font-medium text-brand-strong hover:underline"
                >
                  Verify your business
                </Link>
              )
            }
          />
        </SettingRows>
      </Section>

      {STEPS.map((step) => (
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
              vertical={profile.vertical_template ?? null}
            />
          )}
        />
      ))}
    </div>
  );
}
