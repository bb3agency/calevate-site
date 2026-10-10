"use client";

/**
 * `/auth/account`: a client user's own sign-in. Verify the address, change the password,
 * end sessions (D-174).
 *
 * The client-realm twin of `/auth/admin`. It does not carry the idle-timeout modal: §5.6
 * puts that on the admin realm only (30 minutes idle there against 12 hours here, because
 * the blast radii differ by an order of magnitude).
 *
 * It is not the client dashboard: that lives at `/c/<slug>` and authenticates with the
 * same first-party session this page manages (`authn/cookies.read_token`, D-177).
 *
 * Layout (REDESIGN-2): a header naming the person and the account, then label–value
 * settings rows in three plain sections on the white ground. No cards, no always-open
 * forms; the password form opens in place from its row, and "Sign out everywhere" asks.
 */

import type { ReactNode } from "react";

import type { UseQueryResult } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Providers } from "@/app/providers";
import { AuthPageFrame } from "@/components/authPage";
import { BACK_LINK, EmailRow, SessionsSection } from "@/components/authn/accountSections";
import { AuthProblemNotice } from "@/components/authn/fields";
import { PasswordRow } from "@/components/authn/passwordRow";
import { AccountPageSkeleton, AccountRowsSkeleton, IdentityBars } from "@/components/authn/skeletons";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { StatusPill } from "@/components/console/statusPill";
import type { Me } from "@/lib/api/client";
import { useUnscopedMe } from "@/lib/api/hooks";
import { CLIENT_SIGN_IN_PATH, clientAuthn } from "@/lib/authn/clientAuthn";
import {
  ClientSessionGate,
  ClientSessionProvider,
  useClientSession,
} from "@/lib/authn/clientSession";

export default function ClientAccountPage() {
  return (
    <Providers>
      <ClientSessionProvider>
        <AuthPageFrame realmLabel="Client console" width="wide" ground="surface">
          <div>
            {/* `/c` rather than `/c/<slug>`, even when the slug is on screen: `/c` is the
                junction that resolves "which console is mine" and already renders every
                failure of that question, including the read this page could not make. */}
            <header className="space-y-3">
              <Link href="/c" className={BACK_LINK}>
                <ArrowLeft aria-hidden className="h-3.5 w-3.5" />
                Back to your console
              </Link>
              <h1 className="text-title text-ink">Your account</h1>
            </header>
            <AccountGate>
              <ClientAccountBody />
            </AccountGate>
          </div>
        </AuthPageFrame>
      </ClientSessionProvider>
    </Providers>
  );
}

/**
 * The realm's fail-closed gate, except that the wait is drawn as this page's own skeleton.
 * Every other state (unreachable, partial, signed out) is the shared gate's.
 */
function AccountGate({ children }: { children: ReactNode }) {
  const { status } = useClientSession();
  if (status === "restoring") return <AccountPageSkeleton />;
  return <ClientSessionGate>{children}</ClientSessionGate>;
}

function ClientAccountBody() {
  const { session, retry } = useClientSession();
  // Who this is and which account the session is in, from the server: the session row
  // itself carries a realm, a subject id and a verified flag, nothing a person recognises.
  // `useUnscopedMe` because this page is inside a session and outside an account.
  const me = useUnscopedMe();

  return (
    <>
      <Identity me={me} />

      <div className="mt-10 space-y-10">
        <Section title="Sign-in">
          <SettingRows className="border-y border-line">
            <EmailRow
              authn={clientAuthn}
              email={me.data?.email}
              verified={session?.email_verified ?? false}
              onVerified={retry}
            />
            {/* The bare call: the client realm has no step-up to answer. */}
            <PasswordRow
              realm="client"
              changePassword={(input) => clientAuthn.changePassword(input)}
            />
          </SettingRows>
        </Section>

        <SessionsSection
          authn={clientAuthn}
          signInPath={CLIENT_SIGN_IN_PATH}
          lifetime="A session ends after 12 hours without activity, and after 14 days regardless."
          everywhereHint="Your phone, other browsers, and this one."
          everywhereConsequence="Every session on this account ends, on every device, including this one. You will need your password to sign in again."
        />

        <Section title="Account">
          <AccountRows me={me} />
        </Section>
      </div>
    </>
  );
}

/**
 * The person (name, else address) in the account, and their role in it, under the
 * heading. In flight is a skeleton and a failed read prints nothing here (the Account
 * section carries the refusal): a placeholder name cannot be told apart from a dead API.
 */
function Identity({ me }: { me: UseQueryResult<Me> }) {
  if (me.error != null) return null;
  if (!me.data) return <IdentityBars />;
  const { organization, role, name } = me.data;
  if (!organization && !role) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-body">
      {name ? <span className="font-medium text-ink [overflow-wrap:anywhere]">{name}</span> : null}
      {name && organization ? <span className="text-ink-faint">in</span> : null}
      {organization && (
        <span
          className={`min-w-0 [overflow-wrap:anywhere] ${name ? "text-ink-muted" : "font-medium text-ink"}`}
        >
          {organization.name}
        </span>
      )}
      {role && <StatusPill className="capitalize">{role}</StatusPill>}
    </div>
  );
}

/** The account's id and what this person may do in it, or why neither can be shown. */
function AccountRows({ me }: { me: UseQueryResult<Me> }) {
  if (me.error != null) {
    return (
      <div className="space-y-3">
        <AuthProblemNotice error={me.error} />
        <p className="text-meta text-ink-muted">
          Your sign-in is fine. This is the separate read that says which account it belongs
          to.{" "}
          <button type="button" className={TEXT_ACTION} onClick={() => void me.refetch()}>
            Try again
          </button>
        </p>
      </div>
    );
  }
  if (!me.data) return <AccountRowsSkeleton />;

  const { organization, role, permissions } = me.data;
  if (!organization && !role) {
    return (
      <p className="text-body text-ink-muted">
        This sign-in is not attached to an account yet. Ask whoever invited you to send the
        invitation again.
      </p>
    );
  }

  return (
    <SettingRows className="border-y border-line">
      {organization && <SettingRow label="Account ID" value={organization.slug} />}
      {role && (
        <SettingRow
          label="What you can do"
          // Derived from the permissions the server sent, not from the role's name: the set
          // is what every gated console control previews itself against (`useWriteAccess`),
          // so this sentence and those controls cannot disagree.
          hint={
            permissions.includes("org:manage")
              ? "You can change this account's settings and invite colleagues."
              : "Settings, billing and the team are your account owner's to change."
          }
        />
      )}
    </SettingRows>
  );
}
